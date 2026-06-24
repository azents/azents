"""ChatGPTOAuthSessionRepository tests."""

import datetime
import uuid

import sqlalchemy as sa
from azcommon.result import Failure, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthSessionStatus,
)
from azents.core.crypto import CredentialCipher
from azents.rdb.models.chatgpt_oauth_session import RDBChatGPTOAuthSession
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from . import ChatGPTOAuthSessionRepository
from .data import ChatGPTOAuthSessionCreate, NotFound

_TEST_KEY = Fernet.generate_key().decode()


def _make_repo() -> ChatGPTOAuthSessionRepository:
    """Create repository for tests."""
    return ChatGPTOAuthSessionRepository(CredentialCipher(_TEST_KEY))


def _next_suffix() -> str:
    """Create test data identifier suffix."""
    return uuid.uuid4().hex[:12]


async def _create_workspace(session: AsyncSession) -> str:
    """Create Workspace for tests and return ID."""
    suffix = _next_suffix()
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(
            name=f"ChatGPT OAuth test WS {suffix}",
            handle=f"chatgpt-oauth-{suffix}",
        ),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, f"chatgpt-oauth-{suffix}")
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession) -> str:
    """Create User for tests and return ID."""
    repo = UserRepository()
    user = await repo.create(
        session,
        UserCreate(email=f"chatgpt-oauth-{_next_suffix()}@example.com"),
    )
    return user.id


async def _create_session(
    session: AsyncSession,
    *,
    method: ChatGPTOAuthConnectionMethod = ChatGPTOAuthConnectionMethod.CALLBACK,
    state: str | None = None,
    expires_at: datetime.datetime | None = None,
) -> tuple[ChatGPTOAuthSessionRepository, str]:
    """Create OAuth session for tests."""
    repo = _make_repo()
    workspace_id = await _create_workspace(session)
    user_id = await _create_user(session)
    suffix = _next_suffix()
    created = await repo.create(
        session,
        ChatGPTOAuthSessionCreate(
            workspace_id=workspace_id,
            user_id=user_id,
            method=method,
            state=state or f"state-{suffix}",
            code_verifier=f"verifier-{suffix}",
            redirect_uri="https://azents.example.com/oauth/callback",
            expires_at=expires_at
            or (datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)),
            device_auth_id=(
                f"device-auth-{suffix}"
                if method == ChatGPTOAuthConnectionMethod.DEVICE
                else None
            ),
            user_code="ABCD-EFGH"
            if method == ChatGPTOAuthConnectionMethod.DEVICE
            else None,
            verification_uri="https://auth.openai.com/codex/device"
            if method == ChatGPTOAuthConnectionMethod.DEVICE
            else None,
            interval_seconds=5
            if method == ChatGPTOAuthConnectionMethod.DEVICE
            else None,
        ),
    )
    return repo, created.id


class TestChatGPTOAuthSessionRepository:
    """ChatGPTOAuthSessionRepository tests."""

    async def test_create_encrypts_session_secrets(
        self, rdb_session: AsyncSession
    ) -> None:
        """Store PKCE verifier and device auth ID encrypted."""
        repo, session_id = await _create_session(
            rdb_session, method=ChatGPTOAuthConnectionMethod.DEVICE
        )

        created = await repo.get_by_id_with_secrets(rdb_session, session_id)
        assert created is not None
        rdb_result = await rdb_session.execute(
            sa.select(RDBChatGPTOAuthSession).where(
                RDBChatGPTOAuthSession.id == session_id
            )
        )
        rdb = rdb_result.scalar_one()

        assert created.code_verifier.startswith("verifier-")
        assert created.device_auth_id is not None
        assert created.device_auth_id.startswith("device-auth-")
        assert rdb.encrypted_code_verifier != created.code_verifier
        assert rdb.encrypted_device_auth_id != created.device_auth_id

    async def test_get_by_id_hides_secrets(self, rdb_session: AsyncSession) -> None:
        """Default fetch result does not include secret value."""
        repo, session_id = await _create_session(rdb_session)

        session = await repo.get_by_id(rdb_session, session_id)

        assert session is not None
        assert not hasattr(session, "code_verifier")
        assert not hasattr(session, "device_auth_id")
        assert session.status == ChatGPTOAuthSessionStatus.PENDING

    async def test_get_pending_by_state(self, rdb_session: AsyncSession) -> None:
        """Fetch pending session by state."""
        state = f"state-{_next_suffix()}"
        repo, session_id = await _create_session(rdb_session, state=state)

        session = await repo.get_pending_by_state(rdb_session, state)

        assert session is not None
        assert session.id == session_id
        assert session.code_verifier.startswith("verifier-")

    async def test_consumed_session_is_not_pending(
        self, rdb_session: AsyncSession
    ) -> None:
        """Session consumed as connected status is excluded from pending state fetch."""
        state = f"state-{_next_suffix()}"
        repo, session_id = await _create_session(rdb_session, state=state)

        result = await repo.consume(rdb_session, session_id)
        pending = await repo.get_pending_by_state(rdb_session, state)

        assert isinstance(result, Success)
        assert result.value.status == ChatGPTOAuthSessionStatus.CONNECTED
        assert pending is None

    async def test_expired_session_is_not_pending(
        self, rdb_session: AsyncSession
    ) -> None:
        """Expired pending session is not fetched by state."""
        state = f"state-{_next_suffix()}"
        repo, _session_id = await _create_session(
            rdb_session,
            state=state,
            expires_at=datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=1),
        )

        pending = await repo.get_pending_by_state(rdb_session, state)

        assert pending is None

    async def test_cancelled_session_cannot_be_consumed(
        self, rdb_session: AsyncSession
    ) -> None:
        """Session already cancelled cannot be returned to connected."""
        repo, session_id = await _create_session(rdb_session)
        cancel_result = await repo.cancel(rdb_session, session_id)

        consume_result = await repo.consume(rdb_session, session_id)
        current = await repo.get_by_id(rdb_session, session_id)

        assert isinstance(cancel_result, Success)
        assert isinstance(consume_result, Failure)
        assert current is not None
        assert current.status == ChatGPTOAuthSessionStatus.CANCELLED

    async def test_cancel_session(self, rdb_session: AsyncSession) -> None:
        """Transition Session to cancelled status."""
        repo, session_id = await _create_session(rdb_session)

        result = await repo.cancel(rdb_session, session_id)

        assert isinstance(result, Success)
        assert result.value.status == ChatGPTOAuthSessionStatus.CANCELLED

    async def test_update_not_found(self, rdb_session: AsyncSession) -> None:
        """Return NotFound when updating nonexistent session."""
        repo = _make_repo()

        result = await repo.consume(rdb_session, "missing-session")

        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)
        assert result.error.session_id == "missing-session"
