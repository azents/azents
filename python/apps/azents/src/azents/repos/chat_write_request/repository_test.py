"""ChatWriteRequestRepository tests."""

import dataclasses
import datetime

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from .data import ChatWriteRequestCreate
from .repository import ChatWriteRequestRepository


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


@dataclasses.dataclass(frozen=True)
class _ChatWriteScope:
    """AgentSession and User identifiers for one repository test."""

    session_id: str
    user_id: str


async def _create_agent_session(
    session: AsyncSession,
    *,
    handle: str,
    slug: str,
) -> _ChatWriteScope:
    """Create AgentSession fixture satisfying ChatWriteRequest FK."""
    workspace_id = await _create_workspace(session, handle)
    user_id = await _create_user(session, f"{handle}@example.com")
    agent_id = await _create_agent(session, workspace_id, slug)
    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    return _ChatWriteScope(session_id=agent_session.id, user_id=user_id)


def _create_payload(
    *,
    session_id: str,
    user_id: str,
    client_request_id: str,
) -> ChatWriteRequestCreate:
    """Make ChatWriteRequest creation payload."""
    return ChatWriteRequestCreate(
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
        scope = await _create_agent_session(
            rdb_session,
            handle="chat-write-request-create",
            slug="chat-write-request-create",
        )
        repo = ChatWriteRequestRepository()

        create_result = await repo.create_idempotent(
            rdb_session,
            _create_payload(
                session_id=scope.session_id,
                user_id=scope.user_id,
                client_request_id="request-1",
            ),
        )

        record = create_result.record
        assert create_result.created is True
        assert len(record.id) == 32
        assert record.session_id == scope.session_id
        assert record.user_id == scope.user_id
        assert record.client_request_id == "request-1"
        assert record.write_type == ChatWriteRequestType.COMMAND
        assert record.accepted_id == "compact"
        assert record.history_reload_required is True
        assert record.created_at >= datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    async def test_create_idempotent_returns_existing_record_on_retry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Retry with same session/user/client_request_id returns existing record."""
        scope = await _create_agent_session(
            rdb_session,
            handle="chat-write-request-retry",
            slug="chat-write-request-retry",
        )
        repo = ChatWriteRequestRepository()
        payload = _create_payload(
            session_id=scope.session_id,
            user_id=scope.user_id,
            client_request_id="request-1",
        )

        first = await repo.create_idempotent(rdb_session, payload)
        second = await repo.create_idempotent(rdb_session, payload)

        assert first.created is True
        assert second.created is False
        assert second.record.id == first.record.id
        assert second.record.payload == first.record.payload
