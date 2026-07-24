"""InputBufferRepository tests."""

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    InputBufferKind,
    InputBufferSchedulingMode,
    LLMProvider,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import InputBufferRepository
from .data import InputBufferCreate


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="InputBuffer test", handle=handle)
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
        name="InputBuffer test agent",
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
    """Create AgentSession fixture satisfying InputBuffer FK."""
    workspace_id = await _create_workspace(session, handle)
    user_id = await _create_user(session, f"{handle}@example.com")
    agent_id = await _create_agent(session, workspace_id, slug)
    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
    agent_session = (
        await AgentSessionRepository().ensure_team_primary_for_agent(
            session, workspace_id=runtime.workspace_id, agent_id=runtime.agent_id
        )
    ).session
    return agent_session.id, user_id, workspace_id


def _create_payload(
    *,
    session_id: str,
    user_id: str,
    content: str,
) -> InputBufferCreate:
    """Make InputBuffer create payload."""
    return InputBufferCreate(
        session_id=session_id,
        kind=InputBufferKind.USER_MESSAGE,
        scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        requested_model_target_label="Quality",
        requested_reasoning_effort=ModelReasoningEffort.HIGH,
        sender_user_id=user_id,
        content=content,
        idempotency_key=None,
        metadata={"timestamp": "2026-05-19T00:00:00+00:00", "source": "chat"},
        action=None,
        attachments=["exchange://file-1"],
        file_parts=[],
    )


class TestInputBufferRepository:
    """InputBufferRepository tests."""

    async def test_create_round_trips_jsonb_fields(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Preserve JSONB snapshot fields without damage on creation."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-create",
            slug="input-buffer-create",
        )
        repo = InputBufferRepository()

        created = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="hello",
            ),
        )

        assert len(created.id) == 32
        assert created.session_id == session_id
        assert created.kind == InputBufferKind.USER_MESSAGE
        assert created.scheduling_mode == InputBufferSchedulingMode.WAKE_SESSION
        assert created.requested_model_target_label == "Quality"
        assert created.requested_reasoning_effort == ModelReasoningEffort.HIGH
        assert created.sender_user_id == user_id
        assert created.content == "hello"
        assert created.idempotency_key is None
        assert created.metadata == {
            "timestamp": "2026-05-19T00:00:00+00:00",
            "source": "chat",
        }
        assert created.attachments == ["exchange://file-1"]
        assert created.created_at is not None

    async def test_pending_queries_use_scheduling_mode_and_kind(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Query scheduling intent independently from the payload kind."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-pending-query",
            slug="input-buffer-pending-query",
        )
        repo = InputBufferRepository()
        wake_payload = _create_payload(
            session_id=session_id,
            user_id=user_id,
            content="wake",
        )
        queue_only_payload = wake_payload.model_copy(
            update={
                "kind": InputBufferKind.AGENT_MESSAGE,
                "scheduling_mode": InputBufferSchedulingMode.QUEUE_ONLY,
                "content": "queue only",
            }
        )
        await repo.create(rdb_session, queue_only_payload)

        assert await repo.has_by_session_id_and_scheduling_mode(
            rdb_session,
            session_id=session_id,
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
        )
        assert not await repo.has_by_session_id_and_scheduling_mode(
            rdb_session,
            session_id=session_id,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        )
        assert await repo.has_by_session_id_and_kind(
            rdb_session,
            session_id=session_id,
            kind=InputBufferKind.AGENT_MESSAGE,
        )
        assert not await repo.has_by_session_id_and_kind(
            rdb_session,
            session_id=session_id,
            kind=InputBufferKind.USER_MESSAGE,
        )

    async def test_list_and_flush_order_by_buffer_id(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Session list and flush ready list use buffer id ASC order."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-list",
            slug="input-buffer-list",
        )
        other_session_id, _, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-list-other",
            slug="input-buffer-list-other",
        )
        repo = InputBufferRepository()
        second = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="second",
            ),
        )
        first = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="first",
            ),
        )
        await repo.create(
            rdb_session,
            _create_payload(
                session_id=other_session_id,
                user_id=user_id,
                content="other",
            ),
        )

        listed = await repo.list_by_session_id(rdb_session, session_id)
        flush_list = await repo.list_for_flush(rdb_session, session_id, limit=1)

        expected = sorted([first.id, second.id])
        assert [item.id for item in listed] == expected
        assert [item.id for item in flush_list] == expected[:1]

    async def test_delete_by_session_and_id_is_session_scoped(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Delete only when both session_id and buffer_id match."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-delete",
            slug="input-buffer-delete",
        )
        other_session_id, _, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-delete-other",
            slug="input-buffer-delete-other",
        )
        repo = InputBufferRepository()
        created = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="delete me",
            ),
        )

        wrong_session_deleted = await repo.delete_by_session_and_id(
            rdb_session,
            other_session_id,
            created.id,
        )
        deleted = await repo.delete_by_session_and_id(
            rdb_session,
            session_id,
            created.id,
        )
        deleted_again = await repo.delete_by_session_and_id(
            rdb_session,
            session_id,
            created.id,
        )

        assert wrong_session_deleted is False
        assert deleted is True
        assert deleted_again is False
        assert await repo.get_by_id(rdb_session, created.id) is None

    async def test_claim_for_flush_and_delete_claimed_are_session_scoped(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Flush claim/delete processes only target session rows in id order."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-claim",
            slug="input-buffer-claim",
        )
        other_session_id, _, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-claim-other",
            slug="input-buffer-claim-other",
        )
        repo = InputBufferRepository()
        second = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="second",
            ),
        )
        first = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="first",
            ),
        )
        other = await repo.create(
            rdb_session,
            _create_payload(
                session_id=other_session_id,
                user_id=user_id,
                content="other",
            ),
        )

        claimed = await repo.lock_oldest_by_session_id(rdb_session, session_id)
        assert claimed is not None
        deleted_count = await repo.delete_claimed_by_ids(
            rdb_session,
            session_id,
            [claimed.id],
        )

        assert claimed.id == sorted([first.id, second.id])[0]
        assert deleted_count == 1
        remaining = await repo.list_by_session_id(rdb_session, session_id)
        assert [item.id for item in remaining] == sorted([first.id, second.id])[1:]
        assert await repo.get_by_id(rdb_session, other.id) is not None

    async def test_direct_session_delete_is_rejected(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Protect pending buffers by rejecting direct AgentSession deletion."""
        session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-cascade",
            slug="input-buffer-cascade",
        )
        repo = InputBufferRepository()
        created = await repo.create(
            rdb_session,
            _create_payload(
                session_id=session_id,
                user_id=user_id,
                content="cascade",
            ),
        )

        with pytest.raises(
            IntegrityError,
            match="session_agents_agent_session_id_fkey",
        ):
            async with rdb_session.begin_nested():
                await rdb_session.execute(
                    sa.delete(RDBAgentSession).where(RDBAgentSession.id == session_id)
                )
                await rdb_session.flush()

        assert await repo.get_by_id(rdb_session, created.id) is not None

    async def test_move_by_session_id_preserves_buffer_identity(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Session rollover transfer preserves buffer id and snapshot."""
        from_session_id, user_id, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-move",
            slug="input-buffer-move",
        )
        from_session = await AgentSessionRepository().get_by_id(
            rdb_session,
            from_session_id,
        )
        assert from_session is not None
        to_session = await AgentSessionRepository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=from_session.workspace_id,
                agent_id=from_session.agent_id,
                title=None,
                primary_kind=None,
            ),
        )
        other_session_id, _, _ = await _create_agent_session(
            rdb_session,
            handle="input-buffer-move-other",
            slug="input-buffer-move-other",
        )
        repo = InputBufferRepository()
        moved_buffer = await repo.create(
            rdb_session,
            _create_payload(
                session_id=from_session_id,
                user_id=user_id,
                content="move me",
            ),
        )
        other_buffer = await repo.create(
            rdb_session,
            _create_payload(
                session_id=other_session_id,
                user_id=user_id,
                content="stay put",
            ),
        )

        moved_count = await repo.move_by_session_id(
            rdb_session,
            from_session_id=from_session_id,
            to_session_id=to_session.id,
        )

        assert moved_count == 1
        assert await repo.list_by_session_id(rdb_session, from_session_id) == []
        moved = await repo.get_by_id(rdb_session, moved_buffer.id)
        assert moved is not None
        assert moved.id == moved_buffer.id
        assert moved.session_id == to_session.id
        assert moved.content == "move me"
        assert moved.requested_model_target_label == "Quality"
        assert moved.requested_reasoning_effort == ModelReasoningEffort.HIGH
        other = await repo.get_by_id(rdb_session, other_buffer.id)
        assert other is not None
        assert other.session_id == other_session_id
