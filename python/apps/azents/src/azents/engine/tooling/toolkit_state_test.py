"""Toolkit State runtime abstraction tests."""

import pytest
from azcommon.result import Success
from pydantic import Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.engine.tooling.toolkit_state import (
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


class ExampleToolkitState(ToolkitStateModel):
    """for tests Toolkit State payload."""

    schema_version: int = 1
    value: int = Field(description="Test value")


class _ConflictOnceRepository(ToolkitStateRepository):
    """Repository that simulates concurrent write on first update store."""

    def __init__(self) -> None:
        """Create test repository."""
        self._delegate = ToolkitStateRepository()
        self._conflicted = False

    async def get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        toolkit_namespace: str,
        state_name: str,
    ) -> ToolkitStateRecord | None:
        """Fetch stored state."""
        return await self._delegate.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=toolkit_namespace,
            state_name=state_name,
        )

    async def save(
        self,
        session: AsyncSession,
        state: ToolkitStateUpsert,
    ) -> ToolkitStateRecord:
        """Cause conflict as if another writer stored right before first CAS update."""
        if state.expected_version is not None and not self._conflicted:
            self._conflicted = True
            await self._delegate.save(
                session,
                state.model_copy(
                    update={"state_json": {"schema_version": 1, "value": 10}}
                ),
            )
            raise ToolkitStateConflictError("simulated conflict")
        return await self._delegate.save(session, state)


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Toolkit State test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
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
        name="Toolkit State test agent",
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
    return agent.id


async def _create_agent_and_session(
    session: AsyncSession, suffix: str
) -> tuple[str, str]:
    """Create AgentRuntime and AgentSession for tests."""
    workspace_id = await _create_workspace(session, f"toolkit-state-{suffix}")
    agent_id = await _create_agent(session, workspace_id, f"toolkit-state-{suffix}")
    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session, workspace_id=runtime.workspace_id, agent_id=runtime.agent_id
    )
    return agent_id, agent_session.id


def _identity(agent_id: str, session_id: str, state_name: str) -> ToolkitStateIdentity:
    """Create test Toolkit State identity."""
    return ToolkitStateIdentity(
        agent_id=agent_id,
        session_id=session_id,
        toolkit_namespace="builtin",
        state_name=state_name,
    )


class TestToolkitStateIdentity:
    """ToolkitStateIdentity tests."""

    def test_identity_has_agent_and_session_id(self) -> None:
        """Toolkit State identity is session-bound."""
        identity = ToolkitStateIdentity(
            agent_id="agent-id",
            session_id="session-id",
            toolkit_namespace="builtin",
            state_name="agents_instructions",
        )

        assert identity.agent_id == "agent-id"
        assert identity.session_id == "session-id"

    def test_session_id_is_required(self) -> None:
        """session_id is required."""
        with pytest.raises(ValidationError):
            ToolkitStateIdentity.model_validate(
                {
                    "agent_id": "agent-id",
                    "toolkit_namespace": "builtin",
                    "state_name": "agents_instructions",
                }
            )

    def test_rejects_blank_identity_fields(self) -> None:
        """Deny empty identity fields."""
        for field_name in [
            "agent_id",
            "session_id",
            "toolkit_namespace",
            "state_name",
        ]:
            payload = {
                "agent_id": "agent-id",
                "session_id": "session-id",
                "toolkit_namespace": "builtin",
                "state_name": "agents_instructions",
            }
            payload[field_name] = " "
            with pytest.raises(ValidationError):
                ToolkitStateIdentity.model_validate(payload)


class TestToolkitStateStore:
    """ToolkitStateStore tests."""

    async def test_pydantic_round_trip(self, rdb_session: AsyncSession) -> None:
        """Store Pydantic model state and load it again."""
        agent_id, session_id = await _create_agent_and_session(
            rdb_session, "round-trip"
        )
        identity = _identity(agent_id, session_id, "example_state")
        handle = ToolkitStateStore(session=rdb_session).handle(
            identity, ExampleToolkitState
        )

        missing = await handle.load(
            default_factory=lambda: ExampleToolkitState(value=1)
        )
        saved = await handle.save(ExampleToolkitState(value=2))
        loaded = await handle.load(default_factory=lambda: ExampleToolkitState(value=1))

        assert missing.value == 1
        assert saved.version == 1
        assert loaded.value == 2

    async def test_invalid_stored_payload_raises_validation_error(
        self, rdb_session: AsyncSession
    ) -> None:
        """Return validation error when stored payload does not match model."""
        agent_id, session_id = await _create_agent_and_session(
            rdb_session, "invalid-payload"
        )
        identity = _identity(agent_id, session_id, "invalid_state")
        await ToolkitStateRepository().save(
            rdb_session,
            ToolkitStateUpsert(
                agent_id=identity.agent_id,
                session_id=identity.session_id,
                toolkit_namespace=identity.toolkit_namespace,
                state_name=identity.state_name,
                state_json={"schema_version": 1, "value": "not-an-int"},
                schema_version=1,
                expected_version=None,
            ),
        )
        handle = ToolkitStateStore(session=rdb_session).handle(
            identity, ExampleToolkitState
        )

        with pytest.raises(ValidationError):
            await handle.load(default_factory=lambda: ExampleToolkitState(value=1))

    async def test_save_reloads_before_replacing_state(
        self, rdb_session: AsyncSession
    ) -> None:
        """save reloads latest state before whole-state replacement."""
        agent_id, session_id = await _create_agent_and_session(
            rdb_session, "optimistic-lock"
        )
        identity = _identity(agent_id, session_id, "versioned_state")
        first_handle = ToolkitStateStore(session=rdb_session).handle(
            identity, ExampleToolkitState
        )
        second_handle = ToolkitStateStore(session=rdb_session).handle(
            identity, ExampleToolkitState
        )

        await first_handle.load(default_factory=lambda: ExampleToolkitState(value=1))
        await second_handle.load(default_factory=lambda: ExampleToolkitState(value=1))
        first_saved = await first_handle.save(ExampleToolkitState(value=2))
        second_saved = await second_handle.save(ExampleToolkitState(value=3))

        reloaded = await first_handle.load(
            default_factory=lambda: ExampleToolkitState(value=1)
        )

        assert first_saved.version == 1
        assert second_saved.version == 2
        assert reloaded.value == 3

    async def test_update_reloads_and_retries_after_conflict(
        self, rdb_session: AsyncSession
    ) -> None:
        """update reapplies mutator to latest state after conflict."""
        agent_id, session_id = await _create_agent_and_session(
            rdb_session, "update-retry"
        )
        identity = _identity(agent_id, session_id, "retry_state")
        store = ToolkitStateStore(
            session=rdb_session,
            repository=_ConflictOnceRepository(),
        )
        handle = store.handle(identity, ExampleToolkitState)
        await handle.save(ExampleToolkitState(value=1))

        saved = await handle.update(
            default_factory=lambda: ExampleToolkitState(value=0),
            mutator=lambda state: state.model_copy(update={"value": state.value + 1}),
        )
        loaded = await handle.load(default_factory=lambda: ExampleToolkitState(value=0))

        assert saved.version == 3
        assert loaded.value == 11
