"""AgentSessionRepository tests."""

import asyncio
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.agent_session.repository as agent_session_repo
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
    RuntimeRunnerState,
    SessionAgentKind,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.session_working_folder import build_session_working_folder_path
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.session_lifecycle_finalizer import (
    SessionLifecycleFinalizerRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
    make_test_model_settings,
)

from .data import AgentSessionCreate, AgentSessionEnsureTeamPrimaryResult
from .repository import AgentSessionRepository


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="AgentSession test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str) -> str:
    """Create User for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
    *,
    runtime_capability: AgentRuntimeCapability = AgentRuntimeCapability.MANAGED,
    workspace_path: str | None = "/runtime",
    create_runtime: bool = True,
) -> str:
    """Create Agent for tests."""

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="AgentSession test agent",
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
    )
    session.add(agent)
    await session.flush()
    if runtime_capability is AgentRuntimeCapability.MANAGED and create_runtime:
        runtime_repository = AgentRuntimeRepository()
        runtime = await runtime_repository.ensure_for_agent(session, agent.id)
        await runtime_repository.record_runner_state(
            session,
            runtime.id,
            RuntimeRunnerState.UNKNOWN,
            1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path=(
                f"{workspace_path}/{slug}" if workspace_path is not None else None
            ),
        )
    return agent.id


async def _bind_root_working_folder(
    session: AsyncSession,
    *,
    repository: AgentSessionRepository,
    agent_id: str,
    session_id: str,
    workspace_root: str,
) -> None:
    """Bind one pending root context for cleanup-specific repository tests."""
    runtime = await AgentRuntimeRepository().get_by_agent_id(session, agent_id)
    locked = await repository.lock_working_folder_binding_by_session_id(
        session,
        session_id=session_id,
    )
    assert runtime is not None
    assert locked is not None
    bound = await repository.bind_pending_working_folder(
        session,
        context_id=locked.context.id,
        expected_agent_id=agent_id,
        expected_agent_runtime_id=runtime.id,
        working_folder_path=build_session_working_folder_path(
            locked.root_session_handle,
            workspace_root=workspace_root,
        ),
    )
    assert bound is not None


class TestAgentSessionRepository:
    """AgentSessionRepository tests."""

    async def test_root_context_without_runtime_uses_none_binding(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Runtime-free Agents create a context without Runtime ownership."""
        workspace_id = await _create_workspace(rdb_session, "root-context-none")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "root-context-none",
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        created = await AgentSessionRepository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        context = await rdb_session.scalar(
            sa.select(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == agent_id,
                RDBSessionAgentContext.workspace_id == workspace_id,
            )
        )

        assert context is not None
        assert context.agent_runtime_id is None
        assert context.working_folder_path is None
        assert (
            context.working_folder_binding_state
            is SessionWorkingFolderBindingState.NONE
        )
        assert created.agent_id == agent_id

    async def test_root_context_managed_without_workspace_path_is_pending(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Managed Agents await Runner workspace evidence before binding."""
        workspace_id = await _create_workspace(rdb_session, "root-context-pending")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "root-context-pending",
            workspace_path=None,
        )

        await AgentSessionRepository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        context = await rdb_session.scalar(
            sa.select(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == agent_id,
                RDBSessionAgentContext.workspace_id == workspace_id,
            )
        )

        assert context is not None
        assert context.agent_runtime_id is not None
        assert context.working_folder_path is None
        assert (
            context.working_folder_binding_state
            is SessionWorkingFolderBindingState.PENDING
        )

    async def test_root_context_managed_without_runtime_row_is_pending(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Managed unconfigured Agents may create pending root contexts."""
        workspace_id = await _create_workspace(
            rdb_session,
            "root-context-pending-no-runtime",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "root-context-pending-no-runtime",
            create_runtime=False,
        )

        await AgentSessionRepository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        context = await rdb_session.scalar(
            sa.select(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == agent_id,
                RDBSessionAgentContext.workspace_id == workspace_id,
            )
        )

        assert context is not None
        assert context.agent_runtime_id is not None
        assert context.working_folder_path is None
        assert (
            context.working_folder_binding_state
            is SessionWorkingFolderBindingState.PENDING
        )

    async def test_root_context_creation_uses_final_authority_cas_after_runtime_fk(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Runtime-first work cannot deadlock with root creation authority fencing."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repository = AgentSessionRepository()
        application_name = f"root-creation-cas-{suffix}"
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"root-context-runtime-cas-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"root-context-runtime-cas-{suffix}",
                workspace_path=None,
            )
            runtime = await AgentRuntimeRepository().get_by_agent_id(
                setup_session,
                agent_id,
            )
            assert runtime is not None
            await setup_session.commit()

        async def create_root_context() -> str:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as create_session:
                await create_session.execute(
                    sa.text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
                try:
                    created = await repository.create(
                        create_session,
                        AgentSessionCreate(
                            workspace_id=workspace_id,
                            product_mode=AgentSessionProductMode.TEAM,
                            associated_user_id=None,
                            agent_id=agent_id,
                            title=None,
                        ),
                    )
                except Exception:
                    await create_session.rollback()
                    raise
                await create_session.commit()
                return created.id

        async def wait_for_runtime_fk() -> None:
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                async with AsyncSession(rdb_engine) as observer:
                    waiting = await observer.scalar(
                        sa.text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name = :application_name
                                  AND wait_event_type = 'Lock'
                                  AND query LIKE 'INSERT INTO session_agent_contexts%'
                            )
                            """
                        ),
                        {"application_name": application_name},
                    )
                if waiting:
                    return
                await asyncio.sleep(0.01)
            raise TimeoutError("Root creation did not reach the Runtime FK boundary")

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as runtime_session:
            locked_runtime_id = await runtime_session.scalar(
                sa.select(RDBAgentRuntime.id)
                .where(RDBAgentRuntime.agent_id == agent_id)
                .with_for_update()
            )
            assert locked_runtime_id == runtime.id
            creation_task = asyncio.create_task(create_root_context())
            await wait_for_runtime_fk()
            updated_agent_id = await runtime_session.scalar(
                sa.update(RDBAgent)
                .where(
                    RDBAgent.id == agent_id,
                    RDBAgent.runtime_capability == AgentRuntimeCapability.MANAGED,
                )
                .values(
                    runtime_capability=AgentRuntimeCapability.REMOVING,
                    runtime_capability_version=(
                        RDBAgent.runtime_capability_version + 1
                    ),
                )
                .returning(RDBAgent.id)
            )
            assert updated_agent_id == agent_id
            await runtime_session.commit()

        with pytest.raises(
            RuntimeError,
            match="Agent Runtime authority changed during Session creation",
        ):
            await asyncio.wait_for(creation_task, timeout=5)

        async with AsyncSession(rdb_engine) as verification_session:
            created_count = await verification_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBAgentSession)
                .where(RDBAgentSession.agent_id == agent_id)
            )
            assert created_count == 0

    async def test_lock_by_id_acquires_agent_parent_before_session(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """An Agent writer cannot deadlock with a concurrent Session lock."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repository = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"session-parent-lock-order-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"session-parent-lock-order-{suffix}",
            )
            created = await repository.create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            await setup_session.commit()

        competing_started = asyncio.Event()

        async def lock_session() -> str:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as competing_session:
                competing_started.set()
                locked = await repository.lock_by_id(competing_session, created.id)
                assert locked is not None
                await competing_session.commit()
                return locked.id

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as agent_holder:
            locked_agent_id = await agent_holder.scalar(
                sa.select(RDBAgent.id).where(RDBAgent.id == agent_id).with_for_update()
            )
            assert locked_agent_id == agent_id
            competing_lock = asyncio.create_task(lock_session())
            await asyncio.wait_for(competing_started.wait(), timeout=5)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(competing_lock),
                    timeout=0.1,
                )

            locked = await asyncio.wait_for(
                repository.lock_by_id(agent_holder, created.id),
                timeout=5,
            )
            assert locked is not None
            await agent_holder.commit()

        assert await asyncio.wait_for(competing_lock, timeout=5) == created.id

    async def test_root_context_rejects_runtime_removing(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Runtime removal fences root context admission."""
        workspace_id = await _create_workspace(rdb_session, "root-context-removing")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "root-context-removing",
            runtime_capability=AgentRuntimeCapability.REMOVING,
        )

        with pytest.raises(RuntimeError, match="Runtime is being removed"):
            async with rdb_session.begin_nested():
                await AgentSessionRepository().create(
                    rdb_session,
                    AgentSessionCreate(
                        workspace_id=workspace_id,
                        product_mode=AgentSessionProductMode.TEAM,
                        associated_user_id=None,
                        agent_id=agent_id,
                        title=None,
                    ),
                )

    async def test_pending_context_binds_once_with_root_session_handle(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Pending binding CAS stores one exact root-owned Session folder."""
        workspace_id = await _create_workspace(rdb_session, "pending-bind")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "pending-bind",
            workspace_path=None,
        )
        repository = AgentSessionRepository()
        created = await repository.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        runtime = await AgentRuntimeRepository().get_by_agent_id(
            rdb_session,
            agent_id,
        )
        assert runtime is not None

        locked = await repository.lock_working_folder_binding_by_session_id(
            rdb_session,
            session_id=created.id,
        )

        assert locked is not None
        expected_path = (
            f"/runtime/current/.azents/sessions/{locked.root_session_handle}"
        )
        bound = await repository.bind_pending_working_folder(
            rdb_session,
            context_id=locked.context.id,
            expected_agent_id=agent_id,
            expected_agent_runtime_id=runtime.id,
            working_folder_path=expected_path,
        )
        repeated = await repository.bind_pending_working_folder(
            rdb_session,
            context_id=locked.context.id,
            expected_agent_id=agent_id,
            expected_agent_runtime_id=runtime.id,
            working_folder_path="/runtime/other/.azents/sessions/stale",
        )

        assert bound is not None
        assert bound.binding_state is SessionWorkingFolderBindingState.BOUND
        assert bound.working_folder_path == expected_path
        assert repeated is None
        stored = await repository.get_working_folder_context_by_session_id(
            rdb_session,
            session_id=created.id,
        )
        assert stored is not None
        assert stored.working_folder_path == expected_path

    async def test_pending_context_binding_checks_runtime_identity(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A stale logical Runtime cannot bind a pending root context."""
        workspace_id = await _create_workspace(rdb_session, "pending-bind-runtime")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "pending-bind-runtime",
            workspace_path=None,
        )
        repository = AgentSessionRepository()
        created = await repository.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        locked = await repository.lock_working_folder_binding_by_session_id(
            rdb_session,
            session_id=created.id,
        )
        assert locked is not None

        bound = await repository.bind_pending_working_folder(
            rdb_session,
            context_id=locked.context.id,
            expected_agent_id=agent_id,
            expected_agent_runtime_id="stale-runtime",
            working_folder_path=(
                f"/runtime/current/.azents/sessions/{locked.root_session_handle}"
            ),
        )

        assert bound is None
        stored = await repository.get_working_folder_context_by_session_id(
            rdb_session,
            session_id=created.id,
        )
        assert stored is not None
        assert stored.binding_state is SessionWorkingFolderBindingState.PENDING
        assert stored.working_folder_path is None

    async def test_claim_owner_generation_is_monotonic(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Increment the durable ownership evidence once per claim."""
        workspace_id = await _create_workspace(rdb_session, "owner-generation-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "owner-generation")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )

        assert created.owner_generation == 0
        assert await repo.claim_owner_generation(rdb_session, created.id) == 1
        assert await repo.claim_owner_generation(rdb_session, created.id) == 2
        refreshed = await repo.get_by_id(rdb_session, created.id)
        assert refreshed is not None
        assert refreshed.owner_generation == 2

    async def test_claim_owner_generation_rejects_active_child_of_archived_root(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A stale child wake-up cannot reacquire ownership after purge fencing."""
        workspace_id = await _create_workspace(rdb_session, "owner-root-fence-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "owner-root-fence")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="stale-active-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        archived_at = datetime.datetime.now(datetime.UTC)
        await repo.archive_tree(
            rdb_session,
            root_session_id=root_session.id,
            session_ids=[root_session.id],
            archived_at=archived_at,
            purge_after=archived_at,
            policy_revision=1,
            retention_days=0,
        )
        assert (
            await repo.fence_purge_owner_generations(
                rdb_session,
                session_ids=[root_session.id, child.agent_session_id],
            )
            == 2
        )

        with pytest.raises(ValueError, match="Root AgentSession is not active"):
            await repo.claim_owner_generation(rdb_session, child.agent_session_id)

        refreshed_child = await repo.get_by_id(
            rdb_session,
            child.agent_session_id,
        )
        assert refreshed_child is not None
        assert refreshed_child.status is AgentSessionStatus.ACTIVE
        assert refreshed_child.owner_generation == 1

    @pytest.mark.parametrize(
        "locked_session_kind",
        ["root", "target"],
    )
    async def test_claim_owner_generation_avoids_inverse_session_lock_cycle(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
        locked_session_kind: str,
    ) -> None:
        """Owner claim yields its tree lock when a Session is already locked."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"owner-claim-lock-cycle-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"owner-claim-lock-cycle-{suffix}",
            )
            root_session = await repo.create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            root_agent = await repo.get_session_agent_by_session_id(
                setup_session,
                root_session.id,
            )
            assert root_agent is not None
            child = await repo.create_child_session_agent(
                setup_session,
                parent_session_agent_id=root_agent.id,
                name="claim-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            await setup_session.commit()

        claim_started = asyncio.Event()

        async def claim_child_owner() -> int:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as claim_session:
                claim_started.set()
                generation = await repo.claim_owner_generation(
                    claim_session,
                    child.agent_session_id,
                )
                await claim_session.commit()
                return generation

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as session_holder:
            locked_session_id = (
                root_session.id
                if locked_session_kind == "root"
                else child.agent_session_id
            )
            locked_session = await repo.lock_by_id(
                session_holder,
                locked_session_id,
            )
            assert locked_session is not None
            claim_task = asyncio.create_task(claim_child_owner())
            await asyncio.wait_for(claim_started.wait(), timeout=5)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(claim_task),
                    timeout=0.1,
                )

            locked_root_agent = await asyncio.wait_for(
                repo.lock_session_agent_by_id(
                    session_holder,
                    root_agent.id,
                ),
                timeout=5,
            )
            assert locked_root_agent is not None
            await session_holder.commit()

            assert await asyncio.wait_for(claim_task, timeout=5) == 1

    async def test_fence_purge_owner_generations_covers_entire_root_tree(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Root-authoritative purge fences children with stale active status."""
        workspace_id = await _create_workspace(rdb_session, "purge-fence-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "purge-fence")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            created.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="stale-active-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        archived_at = datetime.datetime.now(datetime.UTC)
        await repo.archive_tree(
            rdb_session,
            root_session_id=created.id,
            session_ids=[created.id],
            archived_at=archived_at,
            purge_after=archived_at,
            policy_revision=1,
            retention_days=0,
        )

        fenced_count = await repo.fence_purge_owner_generations(
            rdb_session,
            session_ids=[created.id, child.agent_session_id],
        )

        assert fenced_count == 2
        refreshed_root = await repo.get_by_id(rdb_session, created.id)
        refreshed_child = await repo.get_by_id(rdb_session, child.agent_session_id)
        assert refreshed_root is not None
        assert refreshed_root.status is AgentSessionStatus.ARCHIVED
        assert refreshed_root.owner_generation == 1
        assert refreshed_child is not None
        assert refreshed_child.status is AgentSessionStatus.ACTIVE
        assert refreshed_child.owner_generation == 1

    async def test_last_inference_profile_round_trip(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Persist explicit Default and explicit effort session profiles."""
        workspace_id = await _create_workspace(rdb_session, "session-profile-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-profile")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )

        assert created.inference_state is None

        resolved_at = datetime.datetime.now(datetime.UTC)
        default_state = SessionInferenceState(
            model_target_label="Quality",
            model_selection=make_test_model_selection(),
            model_settings=make_test_model_settings(),
            reasoning_effort=None,
            effective_context_window_tokens=100_000,
            effective_auto_compaction_threshold_tokens=80_000,
            resolved_at=resolved_at,
        )
        default_profile = await repo.set_inference_state(
            rdb_session,
            session_id=created.id,
            inference_state=default_state,
        )
        assert default_profile.inference_state == default_state

        explicit_state = default_state.model_copy(
            update={"reasoning_effort": ModelReasoningEffort.HIGH}
        )
        explicit_profile = await repo.set_inference_state(
            rdb_session,
            session_id=created.id,
            inference_state=explicit_state,
        )
        assert explicit_profile.inference_state == explicit_state

    async def test_ensure_active_creates_one_active_session(
        self, rdb_session: AsyncSession
    ) -> None:
        """Ensure only one active AgentSession per AgentRuntime."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-session-model")
        repo = AgentSessionRepository()

        first_result = await repo.ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        second_result = await repo.ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        first = first_result.session
        second = second_result.session

        assert first_result.created is True
        assert second_result.created is False
        assert first.id == second.id
        assert first.status == AgentSessionStatus.ACTIVE
        assert first.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY
        assert first.title is None
        assert first.handle.count("-") == 2

    async def test_create_retries_duplicate_session_handle(
        self, rdb_session: AsyncSession, monkeypatch: MonkeyPatch
    ) -> None:
        """AgentSession handle generation retries unique constraint conflicts."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-handle-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-handle"
        )
        handles = iter(
            [
                "abandon-ability-able",
                "abandon-ability-able",
                "about-above-absent",
            ]
        )
        monkeypatch.setattr(
            agent_session_repo,
            "generate_session_handle",
            lambda: next(handles),
        )
        repo = AgentSessionRepository()

        first = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        second = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )

        assert first.handle == "abandon-ability-able"
        assert second.handle == "about-above-absent"

    async def test_create_assigns_pending_root_context_working_folder(
        self,
        rdb_session: AsyncSession,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Managed root creation records Runtime ownership without path authority."""
        workspace_id = await _create_workspace(
            rdb_session,
            "working-folder-context-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "working-folder-context",
        )
        monkeypatch.setattr(
            agent_session_repo,
            "generate_session_handle",
            lambda: "cactus-river-window",
        )
        repo = AgentSessionRepository()

        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            created.id,
        )
        assert root_agent is not None
        context = await rdb_session.get(
            RDBSessionAgentContext,
            root_agent.context_id,
        )

        assert context is not None
        assert context.working_folder_path is None
        assert (
            context.working_folder_binding_state
            is SessionWorkingFolderBindingState.PENDING
        )
        assert (
            context.working_folder_cleanup_status
            is SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
        )
        assert context.working_folder_cleanup_summary is None
        assert context.working_folder_cleanup_completed_at is None

    async def test_working_folder_cleanup_transitions_from_pending_to_terminal(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The root context records one bounded archive cleanup attempt."""
        workspace_id = await _create_workspace(
            rdb_session,
            "working-folder-cleanup-transition",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "working-folder-cleanup-transition",
        )
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        await _bind_root_working_folder(
            rdb_session,
            repository=repo,
            agent_id=agent_id,
            session_id=created.id,
            workspace_root="/runtime/working-folder-cleanup-transition",
        )

        pending = await repo.mark_working_folder_cleanup_pending(
            rdb_session,
            root_session_id=created.id,
        )
        assert pending is not None
        completed_at = datetime.datetime.now(datetime.UTC)
        completed = await repo.complete_working_folder_cleanup(
            rdb_session,
            context_id=pending.id,
            status=SessionWorkingFolderCleanupStatus.SUCCEEDED,
            summary="Session working folder cleanup completed: deleted.",
            completed_at=completed_at,
        )
        repeated_pending = await repo.mark_working_folder_cleanup_pending(
            rdb_session,
            root_session_id=created.id,
        )

        assert pending.cleanup_status is SessionWorkingFolderCleanupStatus.PENDING
        assert completed is True
        assert repeated_pending is not None
        assert (
            repeated_pending.cleanup_status
            is SessionWorkingFolderCleanupStatus.SUCCEEDED
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            created.id,
        )
        assert root_agent is not None
        context = await rdb_session.get(RDBSessionAgentContext, root_agent.context_id)
        assert context is not None
        assert (
            context.working_folder_cleanup_status
            is SessionWorkingFolderCleanupStatus.SUCCEEDED
        )
        assert context.working_folder_cleanup_summary == (
            "Session working folder cleanup completed: deleted."
        )
        assert context.working_folder_cleanup_completed_at == completed_at

    async def test_working_folder_cleanup_rejects_nonterminal_status(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Terminalization refuses a nonterminal cleanup status."""
        workspace_id = await _create_workspace(
            rdb_session,
            "working-folder-cleanup-invalid-status",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "working-folder-cleanup-invalid-status",
        )
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        await _bind_root_working_folder(
            rdb_session,
            repository=repo,
            agent_id=agent_id,
            session_id=created.id,
            workspace_root="/runtime/working-folder-cleanup-invalid-status",
        )
        pending = await repo.mark_working_folder_cleanup_pending(
            rdb_session,
            root_session_id=created.id,
        )
        assert pending is not None

        with pytest.raises(ValueError, match="must be terminal"):
            await repo.complete_working_folder_cleanup(
                rdb_session,
                context_id=pending.id,
                status=SessionWorkingFolderCleanupStatus.PENDING,
                summary="not terminal",
                completed_at=datetime.datetime.now(datetime.UTC),
            )

    async def test_restore_tree_resets_working_folder_cleanup_for_rearchive(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Restore clears prior cleanup observations before a new archive attempt."""
        workspace_id = await _create_workspace(
            rdb_session,
            "working-folder-cleanup-restore",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "working-folder-cleanup-restore",
        )
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        await _bind_root_working_folder(
            rdb_session,
            repository=repo,
            agent_id=agent_id,
            session_id=created.id,
            workspace_root="/runtime/working-folder-cleanup-restore",
        )
        pending = await repo.mark_working_folder_cleanup_pending(
            rdb_session,
            root_session_id=created.id,
        )
        assert pending is not None
        completed = await repo.complete_working_folder_cleanup(
            rdb_session,
            context_id=pending.id,
            status=SessionWorkingFolderCleanupStatus.SUCCEEDED,
            summary="Session working folder cleanup completed: deleted.",
            completed_at=datetime.datetime.now(datetime.UTC),
        )
        assert completed is True
        await repo.archive_tree(
            rdb_session,
            root_session_id=created.id,
            session_ids=[created.id],
            archived_at=datetime.datetime.now(datetime.UTC),
            purge_after=None,
            policy_revision=1,
            retention_days=None,
        )

        await repo.restore_tree(
            rdb_session,
            root_session_id=created.id,
            session_ids=[created.id],
        )

        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            created.id,
        )
        assert root_agent is not None
        context = await rdb_session.get(RDBSessionAgentContext, root_agent.context_id)
        assert context is not None
        assert (
            context.working_folder_cleanup_status
            is SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
        )
        assert context.working_folder_cleanup_summary is None
        assert context.working_folder_cleanup_completed_at is None
        assert (
            await repo.mark_working_folder_cleanup_pending(
                rdb_session,
                root_session_id=created.id,
            )
            is not None
        )

    async def test_update_title_round_trips_custom_title(
        self, rdb_session: AsyncSession
    ) -> None:
        """AgentSession title can be updated and cleared."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-title-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-session-title")
        repo = AgentSessionRepository()
        agent_session = (
            await repo.ensure_team_primary_for_agent(
                rdb_session, workspace_id=workspace_id, agent_id=agent_id
            )
        ).session

        titled = await repo.update_title(
            rdb_session,
            session_id=agent_session.id,
            title="Design review",
            title_source=AgentSessionTitleSource.MANUAL,
        )
        cleared = await repo.update_title(
            rdb_session,
            session_id=agent_session.id,
            title=None,
            title_source=None,
        )

        assert titled is not None
        assert titled.title == "Design review"
        assert cleared is not None
        assert cleared.title is None

    async def test_ensure_active_recreates_after_archive(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create new active session when active session is archived."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-archive-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-archive-model"
        )
        repo = AgentSessionRepository()
        first = (
            await repo.ensure_team_primary_for_agent(
                rdb_session, workspace_id=workspace_id, agent_id=agent_id
            )
        ).session
        await repo.archive(
            rdb_session,
            first.id,
            ended_at=datetime.datetime.now(datetime.timezone.utc),
        )

        second = (
            await repo.ensure_team_primary_for_agent(
                rdb_session, workspace_id=workspace_id, agent_id=agent_id
            )
        ).session

        assert second.id != first.id
        assert second.status == AgentSessionStatus.ACTIVE

    async def test_ensure_active_reuses_row_inserted_by_concurrent_transaction(
        self, rdb_engine: AsyncEngine, latest_db_schema: None
    ) -> None:
        """Concurrent ensure_active reuses existing active row."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session, f"agent-session-race-{suffix}"
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"agent-session-race-model-{suffix}",
            )
            await setup_session.commit()

        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as first_session:
            first_result = await repo.ensure_team_primary_for_agent(
                first_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            first = first_result.session

            async with AsyncSession(
                rdb_engine, expire_on_commit=False
            ) as second_session:
                second_started = asyncio.Event()

                async def ensure_second_primary() -> (
                    AgentSessionEnsureTeamPrimaryResult
                ):
                    second_started.set()
                    return await repo.ensure_team_primary_for_agent(
                        second_session, workspace_id=workspace_id, agent_id=agent_id
                    )

                second_task = asyncio.create_task(ensure_second_primary())
                await asyncio.wait_for(second_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(second_task),
                        timeout=0.1,
                    )
                await first_session.commit()
                second_result = await asyncio.wait_for(second_task, timeout=5)
                second = second_result.session
                await second_session.commit()

        assert first_result.created is True
        assert second_result.created is False
        assert second.id == first.id
        assert second.status == AgentSessionStatus.ACTIVE

    async def test_claim_lifecycle_start_sets_marker_once(
        self, rdb_session: AsyncSession
    ) -> None:
        """lifecycle start marker is set only on initial claim."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-session-lifecycle-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-lifecycle-model"
        )
        repo = AgentSessionRepository()
        agent_session = (
            await repo.ensure_team_primary_for_agent(
                rdb_session, workspace_id=workspace_id, agent_id=agent_id
            )
        ).session
        first_claimed_at = datetime.datetime.now(datetime.timezone.utc)
        second_claimed_at = first_claimed_at + datetime.timedelta(seconds=1)

        first_claimed = await repo.claim_lifecycle_start(
            rdb_session,
            agent_session.id,
            now=first_claimed_at,
        )
        second_claimed = await repo.claim_lifecycle_start(
            rdb_session,
            agent_session.id,
            now=second_claimed_at,
        )

        assert first_claimed is True
        assert second_claimed is False
        assert (
            await repo.get_lifecycle_started_at(rdb_session, agent_session.id)
            == first_claimed_at
        )
        refreshed = await repo.get_by_id(rdb_session, agent_session.id)
        assert refreshed is not None
        assert refreshed.lifecycle_started_at == first_claimed_at

    async def test_session_agent_child_tree_creation_and_lookup(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child and nested SessionAgents share one root tree context."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-tree-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-tree")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        assert root_agent.kind == SessionAgentKind.ROOT
        assert root_agent.path == "/root"

        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="reviewer_1",
            agent_type="default",
            title="Reviewer",
            last_task_message="Review this change",
        )
        nested = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=child.id,
            name="fixer-2",
            agent_type="default",
            title=None,
            last_task_message="Fix the review findings",
        )

        assert child.kind == SessionAgentKind.SUBAGENT
        assert child.context_id == root_agent.context_id
        assert child.root_session_agent_id == root_agent.id
        assert child.parent_session_agent_id == root_agent.id
        assert child.path == "/root/reviewer_1"
        assert child.last_task_message == "Review this change"
        assert nested.context_id == root_agent.context_id
        assert nested.root_session_agent_id == root_agent.id
        assert nested.parent_session_agent_id == child.id
        assert nested.path == "/root/reviewer_1/fixer-2"
        assert child.last_message_at is None

        updated_child = await repo.mark_session_agent_message_activity(
            rdb_session,
            session_agent_id=child.id,
        )
        assert updated_child is not None
        assert updated_child.last_message_at is not None

        tree = await repo.list_session_agent_tree(
            rdb_session,
            root_session_agent_id=root_agent.id,
        )
        assert [agent.path for agent in tree] == [
            "/root",
            "/root/reviewer_1",
            "/root/reviewer_1/fixer-2",
        ]
        descendants = await repo.list_descendant_session_agents(
            rdb_session,
            session_agent_id=child.id,
            include_self=False,
        )
        assert [agent.id for agent in descendants] == [nested.id]

        resolved_relative = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=root_agent.id,
            path="reviewer_1/fixer-2",
        )
        resolved_absolute = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=nested.id,
            path="/root/reviewer_1",
        )
        assert resolved_relative is not None
        assert resolved_relative.id == nested.id
        assert resolved_absolute is not None
        assert resolved_absolute.id == child.id

        observed = await repo.update_session_agent_observation_cursor(
            rdb_session,
            session_agent_id=child.id,
            parent_observed_run_index=3,
            parent_observed_event_id="0123456789abcdef0123456789abcdef",
        )
        assert observed is not None
        assert observed.parent_observed_run_index == 3
        assert observed.parent_observed_event_id == "0123456789abcdef0123456789abcdef"

    async def test_session_agent_child_names_are_strict(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child SessionAgent names are strict canonical path segments."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-name-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-name")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None

        for name in ["", "has space", "../x", "x/y", "-bad", "한글", "a" * 65]:
            with pytest.raises(ValueError):
                await repo.create_child_session_agent(
                    rdb_session,
                    parent_session_agent_id=root_agent.id,
                    name=name,
                    agent_type="default",
                    title=None,
                    last_task_message=None,
                )

    async def test_session_agent_duplicate_sibling_is_rejected(
        self, rdb_session: AsyncSession
    ) -> None:
        """Sibling SessionAgents cannot reuse a parent-local name."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-dupe-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-dupe")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        with pytest.raises(ValueError):
            await repo.create_child_session_agent(
                rdb_session,
                parent_session_agent_id=root_agent.id,
                name="worker",
                agent_type="default",
                title=None,
                last_task_message=None,
            )

    async def test_session_agent_child_creation_rejects_archived_root(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Child creation cannot make an archived root tree inconsistent."""
        workspace_id = await _create_workspace(
            rdb_session,
            "session-agent-archived-root-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "session-agent-archived-root",
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        archived_at = datetime.datetime.now(datetime.UTC)
        await repo.archive_tree(
            rdb_session,
            root_session_id=root_session.id,
            session_ids=[root_session.id],
            archived_at=archived_at,
            purge_after=archived_at + datetime.timedelta(days=30),
            policy_revision=1,
            retention_days=30,
        )

        with pytest.raises(ValueError, match="Root AgentSession is not active"):
            await repo.create_child_session_agent(
                rdb_session,
                parent_session_agent_id=root_agent.id,
                name="late-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )

    async def test_session_agent_child_creation_rejects_archived_parent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Nested child creation requires an active direct parent Session."""
        workspace_id = await _create_workspace(
            rdb_session,
            "session-agent-archived-parent-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "session-agent-archived-parent",
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="parent",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        await repo.archive(
            rdb_session,
            child.agent_session_id,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        with pytest.raises(ValueError, match="Parent AgentSession is not active"):
            await repo.create_child_session_agent(
                rdb_session,
                parent_session_agent_id=child.id,
                name="late-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )

    async def test_session_agent_child_creation_rejects_stopping_parent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A stop fence prevents later child work from escaping the subtree stop."""
        workspace_id = await _create_workspace(
            rdb_session,
            "session-agent-stopping-parent-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "session-agent-stopping-parent",
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        await repo.mark_running(rdb_session, root_session.id)
        stopped = await repo.request_stop(
            rdb_session,
            session_id=root_session.id,
            stop_request_id="stop-before-spawn",
            stop_requester_user_id=None,
        )
        assert stopped is not None

        with pytest.raises(ValueError, match="Root AgentSession is stopping"):
            await repo.create_child_session_agent(
                rdb_session,
                parent_session_agent_id=root_agent.id,
                name="late-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )

    async def test_admit_input_wakeup_rejects_a_stop_request_atomically(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Wake admission returns the Session only while input remains eligible."""
        workspace_id = await _create_workspace(
            rdb_session,
            "input-wakeup-cas-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "input-wakeup-cas",
        )
        repo = AgentSessionRepository()
        agent_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )

        admitted = await repo.admit_input_wakeup(rdb_session, agent_session.id)

        assert admitted is not None
        assert admitted.run_state is AgentSessionRunState.RUNNING
        stopped = await repo.request_stop(
            rdb_session,
            session_id=agent_session.id,
            stop_request_id="input-wakeup-stop",
            stop_requester_user_id=None,
        )
        assert stopped is not None

        rejected = await repo.admit_input_wakeup(rdb_session, agent_session.id)

        assert rejected is None

    async def test_subtree_stop_lock_serializes_concurrent_child_creation(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """A child cannot commit outside a concurrently captured stop subtree."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"session-agent-stop-race-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"session-agent-stop-race-{suffix}",
            )
            root_session = await repo.create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            root_agent = await repo.get_session_agent_by_session_id(
                setup_session,
                root_session.id,
            )
            assert root_agent is not None
            await setup_session.commit()

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as stop_session:
            stopped_session_ids = await repo.list_session_agent_subtree_session_ids(
                stop_session,
                agent_session_id=root_session.id,
            )
            assert stopped_session_ids == [root_session.id]
            await repo.mark_running(stop_session, root_session.id)
            stopped = await repo.request_stop(
                stop_session,
                session_id=root_session.id,
                stop_request_id="concurrent-stop",
                stop_requester_user_id=None,
            )
            assert stopped is not None

            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as spawn_session:
                spawn_started = asyncio.Event()

                async def spawn_child() -> object:
                    spawn_started.set()
                    return await repo.create_child_session_agent(
                        spawn_session,
                        parent_session_agent_id=root_agent.id,
                        name="late-child",
                        agent_type="default",
                        title=None,
                        last_task_message=None,
                    )

                spawn_task = asyncio.create_task(spawn_child())
                await asyncio.wait_for(spawn_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(spawn_task),
                        timeout=0.1,
                    )
                await stop_session.commit()
                with pytest.raises(
                    ValueError,
                    match="Root AgentSession is stopping",
                ):
                    await asyncio.wait_for(spawn_task, timeout=5)
                await spawn_session.rollback()

    async def test_parent_stop_lock_serializes_concurrent_nested_child_creation(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """A nested child cannot commit after its parent stop fence."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"session-agent-child-stop-race-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"session-agent-child-stop-race-{suffix}",
            )
            root_session = await repo.create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            root_agent = await repo.get_session_agent_by_session_id(
                setup_session,
                root_session.id,
            )
            assert root_agent is not None
            parent = await repo.create_child_session_agent(
                setup_session,
                parent_session_agent_id=root_agent.id,
                name="parent",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            await repo.mark_running(setup_session, parent.agent_session_id)
            await setup_session.commit()

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as stop_session:
            stopped = await repo.request_stop(
                stop_session,
                session_id=parent.agent_session_id,
                stop_request_id="concurrent-child-stop",
                stop_requester_user_id=None,
            )
            assert stopped is not None

            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as spawn_session:
                spawn_started = asyncio.Event()

                async def spawn_nested_child() -> object:
                    spawn_started.set()
                    return await repo.create_child_session_agent(
                        spawn_session,
                        parent_session_agent_id=parent.id,
                        name="late-grandchild",
                        agent_type="default",
                        title=None,
                        last_task_message=None,
                    )

                spawn_task = asyncio.create_task(spawn_nested_child())
                await asyncio.wait_for(spawn_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(spawn_task),
                        timeout=0.1,
                    )
                await stop_session.commit()
                with pytest.raises(
                    ValueError,
                    match="Parent AgentSession is stopping",
                ):
                    await asyncio.wait_for(spawn_task, timeout=5)
                await spawn_session.rollback()

    async def test_session_agent_path_lookup_is_root_tree_scoped(
        self, rdb_session: AsyncSession
    ) -> None:
        """Path lookup does not cross root SessionAgent trees."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-scope-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-scope")
        repo = AgentSessionRepository()
        first_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        second_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        first_root = await repo.get_session_agent_by_session_id(
            rdb_session,
            first_session.id,
        )
        second_root = await repo.get_session_agent_by_session_id(
            rdb_session,
            second_session.id,
        )
        assert first_root is not None
        assert second_root is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=first_root.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        resolved_from_second_tree = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=second_root.id,
            path=child.path,
        )

        assert resolved_from_second_tree is None

    async def test_child_agent_sessions_are_hidden_from_ordinary_lists(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child AgentSessions are hidden by session_kind from ordinary lists."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-hidden-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "session-agent-hidden"
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        workspace_sessions = await repo.list_by_workspace(rdb_session, workspace_id)
        active_sessions = await repo.list_active_by_agent_id(rdb_session, agent_id)
        child_session = await repo.get_by_id(rdb_session, child.agent_session_id)

        assert [session.id for session in workspace_sessions] == [root_session.id]
        assert [session.id for session in active_sessions] == [root_session.id]
        assert child_session is not None
        assert child_session.session_kind == AgentSessionKind.SUBAGENT

    async def test_delete_session_agent_subtree_deletes_child_sessions(
        self, rdb_session: AsyncSession
    ) -> None:
        """Deleting a linked AgentSession deletes the SessionAgent subtree sessions."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-delete-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "session-agent-delete"
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        nested = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=child.id,
            name="nested",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
            rdb_session,
            root_session_id=root_session.id,
            session_ids=[
                root_session.id,
                child.agent_session_id,
                nested.agent_session_id,
            ],
        )

        assert await repo.get_by_id(rdb_session, root_session.id) is None
        assert await repo.get_by_id(rdb_session, child.agent_session_id) is None
        assert await repo.get_by_id(rdb_session, nested.agent_session_id) is None
        assert await repo.get_session_agent_by_id(rdb_session, root_agent.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, child.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, nested.id) is None

    async def test_finalizer_requires_external_channel_roots_to_be_absent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Finalization never relies on FK cascades for external lifecycle roots."""
        workspace_id = await _create_workspace(
            rdb_session,
            "session-finalizer-external-root-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "session-finalizer-external-root",
        )
        session_repository = AgentSessionRepository()
        agent_session = await session_repository.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        connection = RDBExternalChannelConnection(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            status=ExternalChannelConnectionStatus.ACTIVE,
            app_mode=ExternalChannelAppMode.SINGLE,
        )
        rdb_session.add(connection)
        await rdb_session.flush()
        route = RDBExternalChannelAgentRoute(
            connection_id=connection.id,
            agent_id=agent_id,
            agent_id_snapshot=agent_id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
            connection_app_mode=ExternalChannelAppMode.SINGLE,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
        )
        resource = RDBExternalChannelResource(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="thread-1",
            status=ExternalChannelResourceStatus.ACTIVE,
        )
        rdb_session.add_all((route, resource))
        await rdb_session.flush()
        binding = RDBExternalChannelBinding(
            resource_id=resource.id,
            route_id=route.id,
            agent_session_id=agent_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        )
        rdb_session.add(binding)
        await rdb_session.flush()

        with pytest.raises(
            RuntimeError,
            match="External Channel bindings remain for the purged Session tree",
        ):
            await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                rdb_session,
                root_session_id=agent_session.id,
                session_ids=[agent_session.id],
            )

        remaining = await session_repository.get_by_id(rdb_session, agent_session.id)
        assert remaining is not None

    async def test_create_team_root_sets_product_mode(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Team roots persist explicit product mode without an associated user."""
        workspace_id = await _create_workspace(rdb_session, "product-mode-team-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "product-mode-team")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        assert created.product_mode is AgentSessionProductMode.TEAM
        assert created.associated_user_id is None

    async def test_create_user_root_and_list_predicates(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """User roots are excluded from Team lists and visible in owner lists."""
        workspace_id = await _create_workspace(rdb_session, "product-mode-user-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "product-mode-user")
        owner_id = await _create_user(rdb_session, "owner@example.com")
        other_id = await _create_user(rdb_session, "other@example.com")
        repo = AgentSessionRepository()
        team = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="team",
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        user_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="mine",
                product_mode=AgentSessionProductMode.USER,
                associated_user_id=owner_id,
            ),
        )
        team_list = await repo.list_active_by_agent_id(rdb_session, agent_id)
        assert [item.id for item in team_list] == [team.id]
        owner_list = await repo.list_active_user_by_agent_and_user(
            rdb_session,
            agent_id=agent_id,
            associated_user_id=owner_id,
        )
        assert [item.id for item in owner_list] == [user_session.id]
        other_list = await repo.list_active_user_by_agent_and_user(
            rdb_session,
            agent_id=agent_id,
            associated_user_id=other_id,
        )
        assert other_list == []

    async def test_active_team_lists_order_primary_then_pinned_then_recency(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Active Team directory pages retain pinned-first deterministic ordering."""
        workspace_id = await _create_workspace(rdb_session, "pinned-order-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "pinned-order")
        repo = AgentSessionRepository()
        primary = (
            await repo.ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        pinned_older = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="Pinned older",
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        pinned_newer = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="Pinned newer",
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        unpinned_newer = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="Unpinned newer",
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        unpinned_older = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title="Unpinned older",
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        ordered_updates = [
            (pinned_older, True, 2),
            (pinned_newer, True, 4),
            (unpinned_newer, False, 5),
            (unpinned_older, False, 1),
        ]
        for session, pinned, day in ordered_updates:
            changed_at = datetime.datetime(2026, 1, day, tzinfo=datetime.UTC)
            await rdb_session.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == session.id)
                .values(
                    pinned=pinned,
                    last_user_input_at=changed_at,
                    updated_at=changed_at,
                )
            )
        await rdb_session.flush()

        expected_ids = [
            primary.id,
            pinned_newer.id,
            pinned_older.id,
            unpinned_newer.id,
            unpinned_older.id,
        ]
        active_sessions = await repo.list_active_by_agent_id(
            rdb_session,
            agent_id,
        )
        first_page = await repo.list_active_unread_page_by_agent_id(
            rdb_session,
            agent_id,
            auto_archive_ttl_days=30,
            offset=0,
            limit=2,
        )
        second_page = await repo.list_active_unread_page_by_agent_id(
            rdb_session,
            agent_id,
            auto_archive_ttl_days=30,
            offset=2,
            limit=2,
        )
        third_page = await repo.list_active_unread_page_by_agent_id(
            rdb_session,
            agent_id,
            auto_archive_ttl_days=30,
            offset=4,
            limit=2,
        )

        assert [session.id for session in active_sessions] == expected_ids
        assert [item.session.id for item in first_page.items] == expected_ids[:2]
        assert [item.session.id for item in second_page.items] == expected_ids[2:4]
        assert [item.session.id for item in third_page.items] == expected_ids[4:]
        assert first_page.total_count == len(expected_ids)

    async def test_create_rejects_invalid_product_mode_combinations(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Invalid root/subagent ownership combinations fail closed."""
        workspace_id = await _create_workspace(rdb_session, "product-mode-invalid-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "product-mode-invalid",
        )
        owner_id = await _create_user(rdb_session, "invalid-owner@example.com")
        repo = AgentSessionRepository()
        with pytest.raises(ValueError, match="associated user"):
            await repo.create(
                rdb_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=owner_id,
                ),
            )
        with pytest.raises(ValueError, match="require an associated user"):
            await repo.create(
                rdb_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    product_mode=AgentSessionProductMode.USER,
                    associated_user_id=None,
                ),
            )
        with pytest.raises(ValueError, match="primary kind"):
            await repo.create(
                rdb_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
                    product_mode=AgentSessionProductMode.USER,
                    associated_user_id=owner_id,
                ),
            )
        with pytest.raises(ValueError, match="Subagent sessions"):
            await repo.create(
                rdb_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    session_kind=AgentSessionKind.SUBAGENT,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                ),
            )
