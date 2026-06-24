"""ChatWriteRequestRepository tests."""

import datetime

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatWriteRequestRepository
from .data import ChatWriteRequestCreate


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="ChatWriteRequest test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str) -> str:
    """Create User for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


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
        name="ChatWriteRequest test agent",
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


async def _create_agent_session(
    session: AsyncSession,
    *,
    handle: str,
    slug: str,
) -> tuple[str, str, str]:
    """Create AgentSession fixture satisfying ChatWriteRequest FK."""
    workspace_id = await _create_workspace(session, handle)
    user_id = await _create_user(session, f"{handle}@example.com")
    agent_id = await _create_agent(session, workspace_id, slug)
    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
    agent_session = await AgentSessionRepository().ensure_active(session, runtime.id)
    return agent_session.id, runtime.id, user_id


def _create_payload(
    *,
    session_id: str,
    agent_runtime_id: str,
    user_id: str,
    client_request_id: str,
) -> ChatWriteRequestCreate:
    """Make ChatWriteRequest creation payload."""
    return ChatWriteRequestCreate(
        agent_runtime_id=agent_runtime_id,
        session_id=session_id,
        user_id=user_id,
        client_request_id=client_request_id,
        write_type=ChatWriteRequestType.COMMAND,
        accepted_type=ChatWriteRequestType.COMMAND,
        accepted_id="compact",
        history_reload_required=True,
        payload={"agent_id": "agent-1", "command": "compact"},
    )


class TestChatWriteRequestRepository:
    """ChatWriteRequestRepository tests."""

    async def test_create_idempotent_returns_created_record(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """First request creates record and returns created=True."""
        session_id, runtime_id, user_id = await _create_agent_session(
            rdb_session,
            handle="chat-write-request-create",
            slug="chat-write-request-create",
        )
        repo = ChatWriteRequestRepository()

        record, created = await repo.create_idempotent(
            rdb_session,
            _create_payload(
                session_id=session_id,
                agent_runtime_id=runtime_id,
                user_id=user_id,
                client_request_id="request-1",
            ),
        )

        assert created is True
        assert len(record.id) == 32
        assert record.session_id == session_id
        assert record.agent_runtime_id == runtime_id
        assert record.user_id == user_id
        assert record.client_request_id == "request-1"
        assert record.write_type == ChatWriteRequestType.COMMAND
        assert record.accepted_id == "compact"
        assert record.history_reload_required is True
        assert record.created_at >= datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    async def test_create_idempotent_returns_existing_record_on_retry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Retry with same runtime/user/client_request_id returns existing record."""
        session_id, runtime_id, user_id = await _create_agent_session(
            rdb_session,
            handle="chat-write-request-retry",
            slug="chat-write-request-retry",
        )
        repo = ChatWriteRequestRepository()
        payload = _create_payload(
            session_id=session_id,
            agent_runtime_id=runtime_id,
            user_id=user_id,
            client_request_id="request-1",
        )

        first, first_created = await repo.create_idempotent(rdb_session, payload)
        second, second_created = await repo.create_idempotent(rdb_session, payload)

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert second.payload == first.payload
