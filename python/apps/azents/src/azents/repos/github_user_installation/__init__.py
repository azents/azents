"""GitHub per-user Installation Repository."""

from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from azents.core.github_installation import GitHubInstallationSnapshot
from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.session_capabilities import ReadSession


class GithubUserInstallationRepository:
    """GitHub per-user Installation store."""

    async def sync(
        self,
        session: ReadSession,
        user_id: str,
        platform_app_id: str,
        installations: Sequence[GitHubInstallationSnapshot],
    ) -> None:
        """Synchronize one user's installation list for one Platform App."""
        if not platform_app_id:
            raise ValueError("Platform GitHub App ID is required.")

        api_installation_ids: set[int] = set()

        for inst in installations:
            inst_id = inst.installation_id
            login = inst.account_login
            account_type = inst.account_type
            avatar_url = (
                inst.account_avatar_url if inst.account_avatar_url is not None else ""
            )

            api_installation_ids.add(inst_id)
            stmt = insert(RDBGithubUserInstallation).values(
                id=uuid7().hex,
                user_id=user_id,
                platform_app_id=platform_app_id,
                installation_id=inst_id,
                account_login=login,
                account_type=account_type,
                account_avatar_url=avatar_url,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    RDBGithubUserInstallation.user_id,
                    RDBGithubUserInstallation.platform_app_id,
                    RDBGithubUserInstallation.installation_id,
                ],
                set_={
                    "account_login": login,
                    "account_type": account_type,
                    "account_avatar_url": avatar_url,
                    "updated_at": sa.func.now(),
                },
            )
            await session.read_session.execute(stmt)

        if api_installation_ids:
            await session.read_session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                    RDBGithubUserInstallation.platform_app_id == platform_app_id,
                    RDBGithubUserInstallation.installation_id.notin_(
                        api_installation_ids
                    ),
                )
            )
        else:
            await session.read_session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                    RDBGithubUserInstallation.platform_app_id == platform_app_id,
                )
            )

    async def has_access(
        self,
        session: ReadSession,
        user_id: str,
        platform_app_id: str,
        installation_id: int,
    ) -> bool:
        """Check App-scoped installation ownership."""
        result = await session.read_session.execute(
            select(RDBGithubUserInstallation.id).where(
                RDBGithubUserInstallation.user_id == user_id,
                RDBGithubUserInstallation.platform_app_id == platform_app_id,
                RDBGithubUserInstallation.installation_id == installation_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_accessible_installation_ids(
        self,
        session: ReadSession,
        *,
        user_id: str,
        platform_app_id: str,
        installation_ids: frozenset[int],
    ) -> frozenset[int]:
        """Return selected App-scoped installation authority rows."""
        if not installation_ids:
            return frozenset()
        result = await session.read_session.execute(
            select(RDBGithubUserInstallation.installation_id).where(
                RDBGithubUserInstallation.user_id == user_id,
                RDBGithubUserInstallation.platform_app_id == platform_app_id,
                RDBGithubUserInstallation.installation_id.in_(installation_ids),
            )
        )
        return frozenset(result.scalars().all())
