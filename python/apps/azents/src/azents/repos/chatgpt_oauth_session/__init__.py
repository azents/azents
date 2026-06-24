"""ChatGPT OAuth session repository."""

import datetime

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import ChatGPTOAuthSessionStatus
from azents.core.crypto import CredentialCipher
from azents.rdb.models.chatgpt_oauth_session import RDBChatGPTOAuthSession

from .data import (
    ChatGPTOAuthSession,
    ChatGPTOAuthSessionCreate,
    ChatGPTOAuthSessionWithSecrets,
    NotFound,
)


class ChatGPTOAuthSessionRepository:
    """ChatGPT OAuth session CRUD repository."""

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self._cipher = cipher

    async def create(
        self,
        session: AsyncSession,
        create: ChatGPTOAuthSessionCreate,
    ) -> ChatGPTOAuthSession:
        """Create ChatGPT OAuth session.

        :param session: Database session
        :param create: Create data
        :return: Created session
        """
        rdb_session = RDBChatGPTOAuthSession(
            workspace_id=create.workspace_id,
            user_id=create.user_id,
            method=create.method,
            state=create.state,
            encrypted_code_verifier=self._cipher.encrypt(create.code_verifier),
            redirect_uri=create.redirect_uri,
            encrypted_device_auth_id=(
                self._cipher.encrypt(create.device_auth_id)
                if create.device_auth_id is not None
                else None
            ),
            user_code=create.user_code,
            verification_uri=create.verification_uri,
            interval_seconds=create.interval_seconds,
            expires_at=create.expires_at,
        )
        session.add(rdb_session)
        await session.flush()
        return self._build(rdb_session)

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> ChatGPTOAuthSession | None:
        """Fetch ChatGPT OAuth session by ID.

        :param session: Database session
        :param session_id: Session ID
        :return: Session or None
        """
        rdb = await session.get(RDBChatGPTOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_with_secrets(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> ChatGPTOAuthSessionWithSecrets | None:
        """Fetch ChatGPT OAuth session by ID including secret.

        :param session: Database session
        :param session_id: Session ID
        :return: Session including secret or None
        """
        rdb = await session.get(RDBChatGPTOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build_with_secrets(rdb)

    async def get_pending_by_state(
        self,
        session: AsyncSession,
        state: str,
    ) -> ChatGPTOAuthSessionWithSecrets | None:
        """Fetch pending ChatGPT OAuth session by State.

        :param session: Database session
        :param state: OAuth state
        :return: Pending session including secret or None
        """
        result = await session.execute(
            sa.select(RDBChatGPTOAuthSession).where(
                RDBChatGPTOAuthSession.state == state,
                RDBChatGPTOAuthSession.status == ChatGPTOAuthSessionStatus.PENDING,
                RDBChatGPTOAuthSession.expires_at > datetime.datetime.now(datetime.UTC),
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_with_secrets(rdb)

    async def consume(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[ChatGPTOAuthSession, NotFound]:
        """Transition pending session to connected status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            ChatGPTOAuthSessionStatus.CONNECTED,
        )

    async def cancel(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[ChatGPTOAuthSession, NotFound]:
        """Transition pending session to cancelled status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            ChatGPTOAuthSessionStatus.CANCELLED,
        )

    async def _transition_pending(
        self,
        session: AsyncSession,
        session_id: str,
        status: ChatGPTOAuthSessionStatus,
    ) -> Result[ChatGPTOAuthSession, NotFound]:
        """Transition status of unexpired pending session."""
        result = await session.execute(
            sa.update(RDBChatGPTOAuthSession)
            .where(
                RDBChatGPTOAuthSession.id == session_id,
                RDBChatGPTOAuthSession.status == ChatGPTOAuthSessionStatus.PENDING,
                RDBChatGPTOAuthSession.expires_at > datetime.datetime.now(datetime.UTC),
            )
            .values(status=status)
            .returning(RDBChatGPTOAuthSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(session_id=session_id))
        return Success(self._build(rdb))

    def _build(self, rdb: RDBChatGPTOAuthSession) -> ChatGPTOAuthSession:
        """Convert RDB model to domain model."""
        return ChatGPTOAuthSession(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            user_id=rdb.user_id,
            method=rdb.method,
            state=rdb.state,
            redirect_uri=rdb.redirect_uri,
            user_code=rdb.user_code,
            verification_uri=rdb.verification_uri,
            interval_seconds=rdb.interval_seconds,
            status=rdb.status,
            expires_at=rdb.expires_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_with_secrets(
        self,
        rdb: RDBChatGPTOAuthSession,
    ) -> ChatGPTOAuthSessionWithSecrets:
        """Convert RDB model to domain model including secret."""
        base = self._build(rdb)
        device_auth_id = (
            self._cipher.decrypt(rdb.encrypted_device_auth_id)
            if rdb.encrypted_device_auth_id is not None
            else None
        )
        return ChatGPTOAuthSessionWithSecrets(
            **base.model_dump(),
            code_verifier=self._cipher.decrypt(rdb.encrypted_code_verifier),
            device_auth_id=device_auth_id,
        )
