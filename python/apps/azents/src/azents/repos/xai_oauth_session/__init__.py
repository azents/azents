"""xAI OAuth session repository."""

import datetime

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.xai_oauth import XaiOAuthSessionStatus
from azents.rdb.models.xai_oauth_session import RDBXaiOAuthSession

from .data import (
    NotFound,
    XaiOAuthSession,
    XaiOAuthSessionCreate,
    XaiOAuthSessionWithSecrets,
)


class XaiOAuthSessionRepository:
    """xAI OAuth session CRUD repository."""

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self._cipher = cipher

    async def create(
        self,
        session: AsyncSession,
        create: XaiOAuthSessionCreate,
    ) -> XaiOAuthSession:
        """Create xAI OAuth session.

        :param session: Database session
        :param create: Create data
        :return: Created session
        """
        rdb_session = RDBXaiOAuthSession(
            workspace_id=create.workspace_id,
            user_id=create.user_id,
            method=create.method,
            encrypted_device_code=self._cipher.encrypt(create.device_code),
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
    ) -> XaiOAuthSession | None:
        """Fetch xAI OAuth session by ID.

        :param session: Database session
        :param session_id: Session ID
        :return: Session or None
        """
        rdb = await session.get(RDBXaiOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_with_secrets(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> XaiOAuthSessionWithSecrets | None:
        """Fetch xAI OAuth session by ID including secrets.

        :param session: Database session
        :param session_id: Session ID
        :return: Session including secrets or None
        """
        rdb = await session.get(RDBXaiOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build_with_secrets(rdb)

    async def consume(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[XaiOAuthSession, NotFound]:
        """Transition pending session to connected status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            XaiOAuthSessionStatus.CONNECTED,
        )

    async def cancel(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[XaiOAuthSession, NotFound]:
        """Transition pending session to cancelled status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            XaiOAuthSessionStatus.CANCELLED,
        )

    async def _transition_pending(
        self,
        session: AsyncSession,
        session_id: str,
        status: XaiOAuthSessionStatus,
    ) -> Result[XaiOAuthSession, NotFound]:
        """Transition status of unexpired pending session."""
        result = await session.execute(
            sa.update(RDBXaiOAuthSession)
            .where(
                RDBXaiOAuthSession.id == session_id,
                RDBXaiOAuthSession.status == XaiOAuthSessionStatus.PENDING,
                RDBXaiOAuthSession.expires_at > datetime.datetime.now(datetime.UTC),
            )
            .values(status=status)
            .returning(RDBXaiOAuthSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(session_id=session_id))
        return Success(self._build(rdb))

    def _build(self, rdb: RDBXaiOAuthSession) -> XaiOAuthSession:
        """Convert RDB model to domain model."""
        return XaiOAuthSession(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            user_id=rdb.user_id,
            method=rdb.method,
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
        rdb: RDBXaiOAuthSession,
    ) -> XaiOAuthSessionWithSecrets:
        """Convert RDB model to domain model including secrets."""
        base = self._build(rdb)
        return XaiOAuthSessionWithSecrets(
            **base.model_dump(),
            device_code=self._cipher.decrypt(rdb.encrypted_device_code),
        )
