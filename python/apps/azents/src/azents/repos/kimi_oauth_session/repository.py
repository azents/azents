"""Kimi OAuth session repository."""

import datetime

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.kimi_oauth import KimiOAuthSessionStatus
from azents.rdb.models.kimi_oauth_session import RDBKimiOAuthSession

from .data import (
    KimiOAuthSession,
    KimiOAuthSessionCreate,
    KimiOAuthSessionWithSecrets,
    NotFound,
)


class KimiOAuthSessionRepository:
    """Kimi OAuth session CRUD repository."""

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self.cipher = cipher

    async def create(
        self,
        session: AsyncSession,
        create: KimiOAuthSessionCreate,
    ) -> KimiOAuthSession:
        """Create Kimi OAuth session.

        :param session: Database session
        :param create: Create data
        :return: Created session
        """
        rdb_session = RDBKimiOAuthSession(
            workspace_id=create.workspace_id,
            user_id=create.user_id,
            method=create.method,
            encrypted_device_code=self.cipher.encrypt(create.device_code),
            encrypted_device_id=self.cipher.encrypt(create.device_id),
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
    ) -> KimiOAuthSession | None:
        """Fetch Kimi OAuth session by ID.

        :param session: Database session
        :param session_id: Session ID
        :return: Session or None
        """
        rdb = await session.get(RDBKimiOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_with_secrets(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> KimiOAuthSessionWithSecrets | None:
        """Fetch Kimi OAuth session by ID including secrets.

        :param session: Database session
        :param session_id: Session ID
        :return: Session including secrets or None
        """
        rdb = await session.get(RDBKimiOAuthSession, session_id)
        if rdb is None:
            return None
        return self._build_with_secrets(rdb)

    async def increase_poll_interval(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        seconds: int,
    ) -> Result[KimiOAuthSession, NotFound]:
        """Increase the polling interval of an unexpired pending session."""
        result = await session.execute(
            sa.update(RDBKimiOAuthSession)
            .where(
                RDBKimiOAuthSession.id == session_id,
                RDBKimiOAuthSession.status == KimiOAuthSessionStatus.PENDING,
                RDBKimiOAuthSession.expires_at > datetime.datetime.now(datetime.UTC),
            )
            .values(
                interval_seconds=RDBKimiOAuthSession.interval_seconds + seconds,
            )
            .returning(RDBKimiOAuthSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(session_id=session_id))
        return Success(self._build(rdb))

    async def consume(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[KimiOAuthSession, NotFound]:
        """Transition pending session to connected status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            KimiOAuthSessionStatus.CONNECTED,
        )

    async def cancel(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> Result[KimiOAuthSession, NotFound]:
        """Transition pending session to cancelled status.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated session or error
        """
        return await self._transition_pending(
            session,
            session_id,
            KimiOAuthSessionStatus.CANCELLED,
        )

    async def _transition_pending(
        self,
        session: AsyncSession,
        session_id: str,
        status: KimiOAuthSessionStatus,
    ) -> Result[KimiOAuthSession, NotFound]:
        """Transition status of unexpired pending session."""
        result = await session.execute(
            sa.update(RDBKimiOAuthSession)
            .where(
                RDBKimiOAuthSession.id == session_id,
                RDBKimiOAuthSession.status == KimiOAuthSessionStatus.PENDING,
                RDBKimiOAuthSession.expires_at > datetime.datetime.now(datetime.UTC),
            )
            .values(status=status)
            .returning(RDBKimiOAuthSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(session_id=session_id))
        return Success(self._build(rdb))

    def _build(self, rdb: RDBKimiOAuthSession) -> KimiOAuthSession:
        """Convert RDB model to domain model."""
        return KimiOAuthSession(
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
        rdb: RDBKimiOAuthSession,
    ) -> KimiOAuthSessionWithSecrets:
        """Convert RDB model to domain model including secrets."""
        base = self._build(rdb)
        return KimiOAuthSessionWithSecrets(
            **base.model_dump(),
            device_code=self.cipher.decrypt(rdb.encrypted_device_code),
            device_id=self.cipher.decrypt(rdb.encrypted_device_id),
        )
