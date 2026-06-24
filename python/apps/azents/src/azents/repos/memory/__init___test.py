"""MemoryRepository tests."""

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import MemoryRepository
from .data import MemoryCreate, MemoryScope, MemorySummary


async def _create_workspace(session: AsyncSession, handle: str = "mem-test-ws") -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Memory test workspace", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    *,
    model_slug: str = "mem-test-model",
    integration_name: str = "mem-test-integration",
) -> str:
    """Create Agent for tests and return agent_id."""

    llm_integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=integration_name,
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(llm_integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Memory test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=llm_integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{model_slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=llm_integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{model_slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


class TestMemoryRepository:
    """MemoryRepository CRUD tests."""

    async def test_upsert_creates_new_memory(self, rdb_session: AsyncSession) -> None:
        """Create new memory."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-upsert-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-upsert-model",
            integration_name="mem-upsert-int",
        )
        repo = MemoryRepository()

        create = MemoryCreate(
            scope=MemoryScope.AGENT,
            type="project",
            name="test-project",
            description="Test project memory",
            content="Project-related content.",
        )
        memory = await repo.upsert(
            rdb_session, agent_id=agent_id, user_id=None, create=create
        )

        assert memory.id is not None
        assert memory.agent_id == agent_id
        assert memory.user_id is None
        assert memory.scope == MemoryScope.AGENT
        assert memory.type == "project"
        assert memory.name == "test-project"
        assert memory.description == "Test project memory"
        assert memory.content == "Project-related content."
        assert memory.created_at is not None
        assert memory.updated_at is not None

    async def test_upsert_updates_existing_memory(
        self, rdb_session: AsyncSession
    ) -> None:
        """Upsert with same memory name updates existing record."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-upd-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-upd-model",
            integration_name="mem-upd-int",
        )
        repo = MemoryRepository()

        create1 = MemoryCreate(
            scope=MemoryScope.AGENT,
            type="feedback",
            name="my-feedback",
            description="Initial description",
            content="Initial content",
        )
        first = await repo.upsert(
            rdb_session, agent_id=agent_id, user_id=None, create=create1
        )

        create2 = MemoryCreate(
            scope=MemoryScope.AGENT,
            type="reference",
            name="my-feedback",
            description="Updated description",
            content="Updated content",
        )
        second = await repo.upsert(
            rdb_session, agent_id=agent_id, user_id=None, create=create2
        )

        assert second.id == first.id
        assert second.description == "Updated description"
        assert second.content == "Updated content"
        assert second.type == "reference"

    async def test_get_by_name_found(self, rdb_session: AsyncSession) -> None:
        """Fetch existing memory by name."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-get-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-get-model",
            integration_name="mem-get-int",
        )
        repo = MemoryRepository()

        create = MemoryCreate(
            scope=MemoryScope.AGENT,
            type="user",
            name="get-test",
            description="Fetch test",
            content="Fetch test Content",
        )
        await repo.upsert(rdb_session, agent_id=agent_id, user_id=None, create=create)

        found = await repo.get_by_name(
            rdb_session, agent_id=agent_id, user_id=None, name="get-test"
        )
        assert found is not None
        assert found.name == "get-test"
        assert found.description == "Fetch test"

    async def test_get_by_name_not_found(self, rdb_session: AsyncSession) -> None:
        """Fetching nonexistent memory by name returns None."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-nf-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-nf-model",
            integration_name="mem-nf-int",
        )
        repo = MemoryRepository()

        found = await repo.get_by_name(
            rdb_session, agent_id=agent_id, user_id=None, name="nonexistent"
        )
        assert found is None

    async def test_get_by_name_agent_scope_isolation(
        self, rdb_session: AsyncSession
    ) -> None:
        """agent scope memory is not fetched from user scope."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-iso-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-iso-model",
            integration_name="mem-iso-int",
        )
        repo = MemoryRepository()

        # Create in agent scope
        create = MemoryCreate(
            scope=MemoryScope.AGENT,
            type="project",
            name="agent-only",
            description="Agent-only",
            content="Agent-only Content",
        )
        await repo.upsert(rdb_session, agent_id=agent_id, user_id=None, create=create)

        # Try fetching from user scope: should not be found
        found = await repo.get_by_name(
            rdb_session,
            agent_id=agent_id,
            user_id="some-user-id",
            name="agent-only",
        )
        assert found is None

    async def test_list_summaries_basic(self, rdb_session: AsyncSession) -> None:
        """Fetch summary list of multiple memories."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-list-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-list-model",
            integration_name="mem-list-int",
        )
        repo = MemoryRepository()

        for i in range(3):
            create = MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project",
                name=f"list-item-{i}",
                description=f"Description {i}",
                content=f"Content {i}",
            )
            await repo.upsert(
                rdb_session, agent_id=agent_id, user_id=None, create=create
            )

        summaries = await repo.list_summaries(
            rdb_session, agent_id=agent_id, user_id=None
        )
        assert len(summaries) == 3
        assert all(isinstance(s, MemorySummary) for s in summaries)
        # ORDER BY type, name, so name order
        names = [s.name for s in summaries]
        assert names == ["list-item-0", "list-item-1", "list-item-2"]

    async def test_list_summaries_type_filter(self, rdb_session: AsyncSession) -> None:
        """Fetch summary list filtered by type."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-tf-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-tf-model",
            integration_name="mem-tf-int",
        )
        repo = MemoryRepository()

        for mem_type, name in [
            ("project", "proj-1"),
            ("feedback", "fb-1"),
            ("project", "proj-2"),
        ]:
            create = MemoryCreate(
                scope=MemoryScope.AGENT,
                type=mem_type,
                name=name,
                description="Description",
                content="Content",
            )
            await repo.upsert(
                rdb_session, agent_id=agent_id, user_id=None, create=create
            )

        summaries = await repo.list_summaries(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            type="project",
        )
        assert len(summaries) == 2
        assert all(s.type == "project" for s in summaries)

    async def test_list_summaries_scope_isolation(
        self, rdb_session: AsyncSession
    ) -> None:
        """agent scope and user scope lists are separated."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-si-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-si-model",
            integration_name="mem-si-int",
        )
        repo = MemoryRepository()
        user_id = "test-user-123"

        # agent scope
        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project",
                name="agent-mem",
                description="Agent",
                content="Agent Content",
            ),
        )
        # user scope
        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=user_id,
            create=MemoryCreate(
                scope=MemoryScope.USER,
                type="user",
                name="user-mem",
                description="User",
                content="User Content",
            ),
        )

        agent_summaries = await repo.list_summaries(
            rdb_session, agent_id=agent_id, user_id=None
        )
        user_summaries = await repo.list_summaries(
            rdb_session, agent_id=agent_id, user_id=user_id
        )

        assert len(agent_summaries) == 1
        assert agent_summaries[0].name == "agent-mem"
        assert len(user_summaries) == 1
        assert user_summaries[0].name == "user-mem"

    async def test_search_finds_by_name(self, rdb_session: AsyncSession) -> None:
        """Search memory by name."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-sn-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-sn-model",
            integration_name="mem-sn-int",
        )
        repo = MemoryRepository()

        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="reference",
                name="search-target-name",
                description="Other description",
                content="Other content",
            ),
        )

        results = await repo.search(
            rdb_session, agent_id=agent_id, user_id=None, query="target-name"
        )
        assert len(results) == 1
        assert results[0].name == "search-target-name"

    async def test_search_finds_by_description(self, rdb_session: AsyncSession) -> None:
        """Search memory by description."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-sd-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-sd-model",
            integration_name="mem-sd-int",
        )
        repo = MemoryRepository()

        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="feedback",
                name="desc-test",
                description="Description containing special_keyword",
                content="General content",
            ),
        )

        results = await repo.search(
            rdb_session, agent_id=agent_id, user_id=None, query="special_keyword"
        )
        assert len(results) == 1
        assert results[0].name == "desc-test"

    async def test_search_finds_by_content(self, rdb_session: AsyncSession) -> None:
        """Search memory by content."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-sc-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-sc-model",
            integration_name="mem-sc-int",
        )
        repo = MemoryRepository()

        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project",
                name="content-test",
                description="General description",
                content="Body has unique_content_string",
            ),
        )

        results = await repo.search(
            rdb_session, agent_id=agent_id, user_id=None, query="unique_content_string"
        )
        assert len(results) == 1
        assert results[0].name == "content-test"

    async def test_delete_by_name_exists(self, rdb_session: AsyncSession) -> None:
        """Deleting existing memory returns True."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-del-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-del-model",
            integration_name="mem-del-int",
        )
        repo = MemoryRepository()

        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="user",
                name="to-delete",
                description="Delete target",
                content="Content to delete",
            ),
        )

        deleted = await repo.delete_by_name(
            rdb_session, agent_id=agent_id, user_id=None, name="to-delete"
        )
        assert deleted is True

        # Confirm deletion
        found = await repo.get_by_name(
            rdb_session, agent_id=agent_id, user_id=None, name="to-delete"
        )
        assert found is None

    async def test_delete_by_name_not_found(self, rdb_session: AsyncSession) -> None:
        """Deleting nonexistent memory returns False."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-dnf-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-dnf-model",
            integration_name="mem-dnf-int",
        )
        repo = MemoryRepository()

        deleted = await repo.delete_by_name(
            rdb_session, agent_id=agent_id, user_id=None, name="nonexistent"
        )
        assert deleted is False

    async def test_count(self, rdb_session: AsyncSession) -> None:
        """Fetch memory count in scope."""
        workspace_id = await _create_workspace(rdb_session, handle="mem-cnt-ws")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            model_slug="mem-cnt-model",
            integration_name="mem-cnt-int",
        )
        repo = MemoryRepository()
        user_id = "count-user-123"

        # Check initial state
        assert await repo.count(rdb_session, agent_id=agent_id, user_id=None) == 0
        assert await repo.count(rdb_session, agent_id=agent_id, user_id=user_id) == 0

        # Create two in agent scope
        for i in range(2):
            await repo.upsert(
                rdb_session,
                agent_id=agent_id,
                user_id=None,
                create=MemoryCreate(
                    scope=MemoryScope.AGENT,
                    type="project",
                    name=f"count-agent-{i}",
                    description=f"Description {i}",
                    content=f"Content {i}",
                ),
            )

        # Create one in user scope
        await repo.upsert(
            rdb_session,
            agent_id=agent_id,
            user_id=user_id,
            create=MemoryCreate(
                scope=MemoryScope.USER,
                type="user",
                name="count-user-0",
                description="User Description",
                content="User Content",
            ),
        )

        assert await repo.count(rdb_session, agent_id=agent_id, user_id=None) == 2
        assert await repo.count(rdb_session, agent_id=agent_id, user_id=user_id) == 1
