"""GitHub PAT repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.rdb.models.github_pat import RDBGitHubPAT

from .data import GitHubPAT, GitHubPATStatus


class GitHubPATRepository:
    """GitHub PAT CRUD repository.

    Manage PATs encrypted per workspace × user.
    """

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self._cipher = cipher

    async def upsert(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
        token: str,
        github_username: str | None = None,
        display_hint: str | None = None,
        expires_at: datetime.datetime | None = None,
    ) -> GitHubPAT:
        """Store PAT (INSERT ON CONFLICT UPDATE).

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :param token: GitHub PAT (plain text)
        :param github_username: GitHub username
        :param display_hint: Token identification hint
        :param expires_at: Fine-grained PAT expiration date
        :return: Created or updated GitHubPAT
        """
        encrypted_token = self._cipher.encrypt(token)
        values = {
            "id": uuid7().hex,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "encrypted_token": encrypted_token,
            "github_username": github_username,
            "display_hint": display_hint,
            "expires_at": expires_at,
        }
        stmt = (
            pg_insert(RDBGitHubPAT)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_github_pats_workspace_user",
                set_={
                    "encrypted_token": encrypted_token,
                    "github_username": github_username,
                    "display_hint": display_hint,
                    "expires_at": expires_at,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(RDBGitHubPAT)
        )
        result = await session.execute(stmt)
        rdb = result.scalar_one()
        return self._build(rdb)

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> GitHubPAT | None:
        """Fetch PAT by workspace and User ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Decrypted GitHubPAT or None
        """
        result = await session.execute(
            sa.select(RDBGitHubPAT).where(
                RDBGitHubPAT.workspace_id == workspace_id,
                RDBGitHubPAT.user_id == user_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_status_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> GitHubPATStatus:
        """Fetch PAT status by workspace and User ID, excluding token.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: PAT status
        """
        result = await session.execute(
            sa.select(RDBGitHubPAT).where(
                RDBGitHubPAT.workspace_id == workspace_id,
                RDBGitHubPAT.user_id == user_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return GitHubPATStatus(registered=False)
        return GitHubPATStatus(
            registered=True,
            github_username=rdb.github_username,
            display_hint=rdb.display_hint,
            expires_at=rdb.expires_at,
        )

    async def delete_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Delete PAT by workspace and User ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        """
        await session.execute(
            sa.delete(RDBGitHubPAT).where(
                RDBGitHubPAT.workspace_id == workspace_id,
                RDBGitHubPAT.user_id == user_id,
            )
        )

    async def get_token(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> str | None:
        """Fetch only decrypted PAT token for user.

        PerUserTokenStore protocol implementation.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Decrypted PAT or None
        """
        pat = await self.get_by_workspace_and_user(session, workspace_id, user_id)
        if pat is None:
            return None
        return pat.token

    async def delete_token(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Delete PAT for user.

        PerUserTokenStore protocol implementation.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        """
        await self.delete_by_workspace_and_user(session, workspace_id, user_id)

    def _build(self, rdb: RDBGitHubPAT) -> GitHubPAT:
        """Convert RDB model to domain model."""
        return GitHubPAT(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            user_id=rdb.user_id,
            token=self._cipher.decrypt(rdb.encrypted_token),
            github_username=rdb.github_username,
            display_hint=rdb.display_hint,
            expires_at=rdb.expires_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
